//! Qualification of persistent ownership, authentication, and immutability.

use std::fs;
use std::io::{Cursor, Read};
use std::path::PathBuf;
use std::sync::{Arc, Barrier};

use aether_driver::{
    CompilationOptions, DriverRequest, DriverResponse, OptimizationLevel, ProjectPlan,
    ProjectRunRequest, execute,
};
use aether_package::{
    CacheLimits, PackageName, PublishOutcome, RegistryCache, RegistryClient, RegistryPolicy,
    RegistryProtocolMetadata, RegistrySnapshotProvider, add, build_publication, sync, update,
};
use aether_registry::RegistryStore;
use semver::Version;
use sha2::Digest as _;

struct Directory(PathBuf);

impl Directory {
    fn new(label: &str) -> Self {
        static SERIAL: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let path = std::env::temp_dir().join(format!(
            "aether-registry-{label}-{}-{}",
            std::process::id(),
            SERIAL.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
        ));
        fs::create_dir(&path).unwrap();
        Self(path)
    }

    fn write(&self, path: &str, text: &str) {
        let path = self.0.join(path);
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(path, text).unwrap();
    }
}

impl Drop for Directory {
    fn drop(&mut self) {
        make_writable(&self.0);
        fs::remove_dir_all(&self.0).unwrap();
    }
}

fn make_writable(path: &std::path::Path) {
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt as _;
        let mut permissions = fs::metadata(path).unwrap().permissions();
        permissions.set_mode(permissions.mode() | 0o700);
        fs::set_permissions(path, permissions).unwrap();
    }
    if path.is_dir() {
        for entry in fs::read_dir(path).unwrap() {
            make_writable(&entry.unwrap().path());
        }
    }
}

fn publication(name: &str, version: &str, value: i32) -> (Directory, aether_package::Publication) {
    let source = Directory::new("source");
    source.write(
        "aether.toml",
        &format!("[package]\nname={name:?}\nversion={version:?}\n"),
    );
    source.write(
        "src/lib.ae",
        &format!("package {name}; int value(){{return {value};}}"),
    );
    let built = build_publication(&source.0).unwrap();
    (source, built)
}

fn publish(
    store: &RegistryStore,
    token: &str,
    item: &aether_package::Publication,
) -> Result<aether_registry::StoredPublication, String> {
    store.publish(
        &item.name,
        &item.version,
        token,
        &item.checksum,
        &item.archive,
    )
}

#[test]
fn ownership_immutability_retry_yank_and_official_metadata() {
    let storage = Directory::new("storage");
    let store = RegistryStore::open(&storage.0).unwrap();
    store.provision_token("alice", &"a".repeat(32)).unwrap();
    store.provision_token("bob", &"b".repeat(32)).unwrap();
    let (_source, first) = publication("mathLibrary", "1.0.0", 1);
    let created = publish(&store, &"a".repeat(32), &first).unwrap();
    assert_eq!(created.outcome, PublishOutcome::Created);
    assert_eq!(
        publish(&store, &"a".repeat(32), &first).unwrap().outcome,
        PublishOutcome::Identical
    );
    assert!(publish(&store, &"b".repeat(32), &first).is_err());

    let (_changed_source, changed) = publication("mathLibrary", "1.0.0", 2);
    assert!(publish(&store, &"a".repeat(32), &changed).is_err());
    assert_eq!(
        store.archive("mathLibrary", "1.0.0").unwrap(),
        first.archive
    );

    store
        .yank("mathLibrary", "1.0.0", &"a".repeat(32), true)
        .unwrap();
    assert!(store.versions("mathLibrary").unwrap()[0].yanked);
    assert_eq!(
        store.archive("mathLibrary", "1.0.0").unwrap(),
        first.archive
    );
    store.set_official("mathLibrary", "1.0.0", true).unwrap();
    assert!(store.metadata("mathLibrary", "1.0.0").unwrap().official);
}

#[test]
fn authentication_checksum_and_archive_identity_are_revalidated() {
    let storage = Directory::new("validation");
    let store = RegistryStore::open(&storage.0).unwrap();
    let token = "credential-with-enough-entropy";
    store.provision_token("owner", token).unwrap();
    let (_source, item) = publication("safeLibrary", "1.0.0", 1);
    assert!(publish(&store, "wrong-token-that-is-long", &item).is_err());
    assert!(
        store
            .publish(
                &item.name,
                &item.version,
                token,
                "sha256:0000000000000000000000000000000000000000000000000000000000000000",
                &item.archive,
            )
            .unwrap_err()
            .contains("checksum")
    );
    assert!(
        store
            .publish(
                "otherName",
                &item.version,
                token,
                &item.checksum,
                &item.archive
            )
            .unwrap_err()
            .contains("identity")
    );
    let mut invalid = item.archive.clone();
    invalid[0] ^= 1;
    let checksum = format!("sha256:{:x}", sha2::Sha256::digest(&invalid));
    assert!(
        store
            .publish(&item.name, &item.version, token, &checksum, &invalid)
            .is_err()
    );
}

#[test]
fn concurrent_first_publish_has_one_created_version_and_safe_retry() {
    let storage = Directory::new("concurrent");
    let store = Arc::new(RegistryStore::open(&storage.0).unwrap());
    let token = "concurrent-owner-token-value";
    store.provision_token("owner", token).unwrap();
    let (_source, item) = publication("parallelLibrary", "1.0.0", 7);
    let item = Arc::new(item);
    let barrier = Arc::new(Barrier::new(8));
    let threads = (0..8)
        .map(|_| {
            let store = Arc::clone(&store);
            let item = Arc::clone(&item);
            let barrier = Arc::clone(&barrier);
            std::thread::spawn(move || {
                barrier.wait();
                publish(&store, token, &item).unwrap().outcome
            })
        })
        .collect::<Vec<_>>();
    let outcomes = threads
        .into_iter()
        .map(|thread| thread.join().unwrap())
        .collect::<Vec<_>>();
    assert_eq!(
        outcomes
            .iter()
            .filter(|outcome| **outcome == PublishOutcome::Created)
            .count(),
        1
    );
    assert_eq!(store.versions("parallelLibrary").unwrap().len(), 1);
}

#[derive(Clone)]
struct StoreClient(RegistryStore);

impl RegistryClient for StoreClient {
    fn versions(&self, name: &PackageName) -> Result<Vec<aether_package::RegistryVersion>, String> {
        self.0.versions(name.as_str())
    }

    fn metadata(
        &self,
        name: &PackageName,
        version: &Version,
    ) -> Result<RegistryProtocolMetadata, String> {
        self.0.metadata(name.as_str(), &version.to_string())
    }

    fn archive(&self, metadata: &RegistryProtocolMetadata) -> Result<Box<dyn Read + Send>, String> {
        self.0
            .archive(&metadata.name, &metadata.version)
            .map(|bytes| Box::new(Cursor::new(bytes)) as Box<dyn Read + Send>)
    }
}

fn provider(store: &RegistryStore, cache: &Directory) -> RegistrySnapshotProvider {
    RegistrySnapshotProvider::new(
        Arc::new(StoreClient(store.clone())),
        RegistryCache::new(cache.0.clone(), CacheLimits::default()).unwrap(),
        RegistryPolicy::Online,
    )
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn publish_add_sync_run_locked_then_update_end_to_end() {
    let storage = Directory::new("e2e-storage");
    let cache = Directory::new("e2e-cache");
    let consumer = Directory::new("e2e-consumer");
    let store = RegistryStore::open(&storage.0).unwrap();
    let token = "end-to-end-owner-token-value";
    store.provision_token("owner", token).unwrap();

    let (_source_100, version_100) = publication("flowLibrary", "1.0.0", 42);
    publish(&store, token, &version_100).unwrap();
    consumer.write(
        "aether.toml",
        "[package]\nname='consumer'\nversion='1.0.0'\n",
    );
    consumer.write(
        "src/main.ae",
        "import flowLibrary; int main(){return flowLibrary.value()-42;}",
    );

    add(&consumer.0, "flowLibrary", &provider(&store, &cache)).unwrap();
    let graph = sync(&consumer.0, Some(&provider(&store, &cache))).unwrap();
    let plan = ProjectPlan::resolved(graph.root, &graph.packages).unwrap();
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let response = execute(DriverRequest::RunProject(ProjectRunRequest {
            input: plan.clone(),
            compilation: CompilationOptions {
                optimization,
                emits: Vec::new(),
            },
            program_args: Vec::new(),
        }))
        .unwrap();
        let DriverResponse::Ran { status, .. } = response else {
            panic!("expected run response")
        };
        assert!(status.success());
    }
    let locked_100 = fs::read_to_string(consumer.0.join("aether.lock")).unwrap();
    assert!(locked_100.contains("version = \"1.0.0\""));

    let (_source_110, version_110) = publication("flowLibrary", "1.1.0", 43);
    publish(&store, token, &version_110).unwrap();
    sync(&consumer.0, Some(&provider(&store, &cache))).unwrap();
    assert_eq!(
        fs::read_to_string(consumer.0.join("aether.lock")).unwrap(),
        locked_100
    );
    update(&consumer.0, Some(&provider(&store, &cache))).unwrap();
    let updated = fs::read_to_string(consumer.0.join("aether.lock")).unwrap();
    assert!(updated.contains("version = \"1.1.0\""));
}
