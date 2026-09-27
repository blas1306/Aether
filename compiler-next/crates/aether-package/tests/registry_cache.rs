//! Productive registry/CAS tests use a deterministic in-process protocol client.

use std::collections::BTreeMap;
use std::fmt::Write as _;
use std::fs;
use std::io::{Cursor, Read};
use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, AtomicUsize, Ordering};
use std::sync::{Arc, Barrier};

use aether_package::{
    CacheLimits, HttpsRegistryClient, PackageName, RegistryCache, RegistryClient, RegistryPolicy,
    RegistryProtocolMetadata, RegistryProvider, RegistrySnapshotProvider, RegistryVersion, sync,
    update,
};
use semver::Version;
use sha2::{Digest, Sha256};

static SERIAL: AtomicU64 = AtomicU64::new(0);

struct Directory(PathBuf);

impl Directory {
    fn new(label: &str) -> Self {
        let path = std::env::temp_dir().join(format!(
            "aether-registry-{label}-{}-{}",
            std::process::id(),
            SERIAL.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir(&path).unwrap();
        Self(path)
    }
}

impl Drop for Directory {
    fn drop(&mut self) {
        make_writable_tree(&self.0);
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn make_writable_tree(path: &std::path::Path) {
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt as _;
        if let Ok(metadata) = fs::metadata(path) {
            let mut permissions = metadata.permissions();
            permissions.set_mode(permissions.mode() | 0o700);
            let _ = fs::set_permissions(path, permissions);
        }
    }
    if let Ok(entries) = fs::read_dir(path) {
        for entry in entries.flatten() {
            if entry.path().is_dir() {
                make_writable_tree(&entry.path());
            }
        }
    }
}

struct FakeClient {
    metadata: RegistryProtocolMetadata,
    archive: Vec<u8>,
    downloads: AtomicUsize,
}

impl FakeClient {
    fn new(
        name: &str,
        version: &str,
        dependencies: BTreeMap<String, String>,
        archive: Vec<u8>,
    ) -> Self {
        let checksum = format!("sha256:{:x}", Sha256::digest(&archive));
        Self {
            metadata: RegistryProtocolMetadata {
                name: name.to_owned(),
                version: version.to_owned(),
                yanked: false,
                official: false,
                checksum,
                dependencies,
                archive_size: archive.len() as u64,
            },
            archive,
            downloads: AtomicUsize::new(0),
        }
    }
}

impl RegistryClient for FakeClient {
    fn versions(&self, name: &PackageName) -> Result<Vec<RegistryVersion>, String> {
        if name.as_str() != self.metadata.name {
            return Err("missing package".to_owned());
        }
        Ok(vec![RegistryVersion {
            version: self.metadata.version.clone(),
            yanked: self.metadata.yanked,
        }])
    }

    fn metadata(
        &self,
        name: &PackageName,
        version: &Version,
    ) -> Result<RegistryProtocolMetadata, String> {
        if name.as_str() != self.metadata.name || version.to_string() != self.metadata.version {
            return Err("missing exact metadata".to_owned());
        }
        Ok(self.metadata.clone())
    }

    fn archive(&self, _: &RegistryProtocolMetadata) -> Result<Box<dyn Read + Send>, String> {
        self.downloads.fetch_add(1, Ordering::Relaxed);
        Ok(Box::new(Cursor::new(self.archive.clone())))
    }
}

fn manifest(name: &str, version: &str, dependencies: &[(&str, &str)]) -> String {
    let mut value = format!("[package]\nname = \"{name}\"\nversion = \"{version}\"\n");
    if !dependencies.is_empty() {
        value.push_str("\n[dependencies]\n");
        for (dependency, requirement) in dependencies {
            writeln!(value, "{dependency} = \"{requirement}\"").unwrap();
        }
    }
    value
}

fn package_archive(name: &str, version: &str, dependencies: &[(&str, &str)]) -> Vec<u8> {
    tar_bytes(&[
        (
            "aether.toml",
            b'0',
            manifest(name, version, dependencies).as_bytes(),
        ),
        ("src/lib.ae", b'0', format!("package {name}\n").as_bytes()),
        ("README.md", b'0', b"fixture"),
    ])
}

fn tar_bytes(entries: &[(&str, u8, &[u8])]) -> Vec<u8> {
    let mut archive = Vec::new();
    for (path, kind, contents) in entries {
        let mut header = [0_u8; 512];
        assert!(path.len() < 100);
        header[..path.len()].copy_from_slice(path.as_bytes());
        header[100..108].copy_from_slice(b"0000444\0");
        header[108..116].copy_from_slice(b"0000000\0");
        header[116..124].copy_from_slice(b"0000000\0");
        write_octal(&mut header[124..136], contents.len() as u64);
        header[136..148].copy_from_slice(b"00000000000\0");
        header[148..156].fill(b' ');
        header[156] = *kind;
        header[257..263].copy_from_slice(b"ustar\0");
        header[263..265].copy_from_slice(b"00");
        let checksum = header.iter().map(|byte| u64::from(*byte)).sum();
        write_checksum(&mut header[148..156], checksum);
        archive.extend_from_slice(&header);
        archive.extend_from_slice(contents);
        archive.resize(archive.len().div_ceil(512) * 512, 0);
    }
    archive.resize(archive.len() + 1024, 0);
    archive
}

fn write_octal(field: &mut [u8], value: u64) {
    let text = format!("{:0width$o}\0", value, width = field.len() - 1);
    field.copy_from_slice(text.as_bytes());
}

fn write_checksum(field: &mut [u8], value: u64) {
    let text = format!("{value:06o}\0 ");
    field.copy_from_slice(text.as_bytes());
}

fn cache(directory: &Directory, limits: CacheLimits) -> RegistryCache {
    RegistryCache::new(directory.0.join("cache"), limits).unwrap()
}

fn provider(directory: &Directory, client: Arc<FakeClient>) -> RegistrySnapshotProvider {
    RegistrySnapshotProvider::new(
        client,
        cache(directory, CacheLimits::default()),
        RegistryPolicy::Online,
    )
}

#[test]
fn https_is_mandatory_and_redirects_are_fail_closed_by_configuration() {
    assert!(HttpsRegistryClient::new("http://registry.example").is_err());
    assert!(HttpsRegistryClient::new("https://user@registry.example").is_err());
    assert!(HttpsRegistryClient::new("https://registry.example").is_ok());
}

#[test]
fn retrieves_versions_metadata_downloads_and_reuses_verified_cas() {
    let directory = Directory::new("happy");
    let client = Arc::new(FakeClient::new(
        "math",
        "1.2.3",
        BTreeMap::new(),
        package_archive("math", "1.2.3", &[]),
    ));
    let first = provider(&directory, Arc::clone(&client));
    let name = PackageName::new("math").unwrap();
    assert_eq!(first.versions(&name).unwrap()[0].version, "1.2.3");
    let metadata = first
        .metadata(&name, &Version::parse("1.2.3").unwrap())
        .unwrap();
    assert!(metadata.root.join("src/lib.ae").is_file());
    assert_eq!(client.downloads.load(Ordering::Relaxed), 1);

    let second = provider(&directory, Arc::clone(&client));
    second
        .metadata(&name, &Version::parse("1.2.3").unwrap())
        .unwrap();
    assert_eq!(client.downloads.load(Ordering::Relaxed), 1);
}

#[test]
fn checksum_truncation_oversize_and_corrupt_object_fail_closed() {
    let archive = package_archive("math", "1.0.0", &[]);
    for case in ["checksum", "truncated", "oversized"] {
        let directory = Directory::new(case);
        let mut client = FakeClient::new("math", "1.0.0", BTreeMap::new(), archive.clone());
        if case == "checksum" {
            client.metadata.checksum = format!("sha256:{}", "0".repeat(64));
        }
        if case == "truncated" {
            client.metadata.archive_size += 1;
        }
        let limits = if case == "oversized" {
            CacheLimits {
                archive_bytes: 10,
                ..CacheLimits::default()
            }
        } else {
            CacheLimits::default()
        };
        let provider = RegistrySnapshotProvider::new(
            Arc::new(client),
            cache(&directory, limits),
            RegistryPolicy::Online,
        );
        let error = provider
            .metadata(&PackageName::new("math").unwrap(), &Version::new(1, 0, 0))
            .unwrap_err();
        assert!(
            error.contains("checksum")
                || error.contains("truncated")
                || error.contains("size limit"),
            "{error}"
        );
    }

    let directory = Directory::new("corrupt");
    let client = Arc::new(FakeClient::new("math", "1.0.0", BTreeMap::new(), archive));
    let name = PackageName::new("math").unwrap();
    let version = Version::new(1, 0, 0);
    provider(&directory, Arc::clone(&client))
        .metadata(&name, &version)
        .unwrap();
    let digest = client.metadata.checksum.strip_prefix("sha256:").unwrap();
    fs::write(
        directory
            .0
            .join("cache/objects/sha256")
            .join(&digest[..2])
            .join(digest),
        b"corrupt",
    )
    .unwrap();
    let source = directory
        .0
        .join("cache/sources/sha256")
        .join(&digest[..2])
        .join(digest);
    make_writable_tree(&source);
    fs::remove_dir_all(source).unwrap();
    provider(&directory, Arc::clone(&client))
        .metadata(&name, &version)
        .unwrap();
    assert_eq!(client.downloads.load(Ordering::Relaxed), 2);
}

#[test]
fn rejects_traversal_links_special_files_duplicates_and_manifest_mismatch() {
    let cases = [
        ("traversal", tar_bytes(&[("../escape.ae", b'0', b"bad")])),
        ("symlink", tar_bytes(&[("src/lib.ae", b'2', b"")])),
        ("hardlink", tar_bytes(&[("src/lib.ae", b'1', b"")])),
        ("special", tar_bytes(&[("src/device", b'3', b"")])),
        (
            "duplicate",
            tar_bytes(&[("src/lib.ae", b'0', b"a"), ("src//lib.ae", b'0', b"b")]),
        ),
        ("mismatch", package_archive("other", "1.0.0", &[])),
    ];
    for (case, archive) in cases {
        let directory = Directory::new(case);
        let client = Arc::new(FakeClient::new("math", "1.0.0", BTreeMap::new(), archive));
        let error = provider(&directory, client)
            .metadata(&PackageName::new("math").unwrap(), &Version::new(1, 0, 0))
            .unwrap_err();
        assert!(
            error.contains("archive") || error.contains("unsafe") || error.contains("duplicate"),
            "{case}: {error}"
        );
    }
}

#[test]
fn concurrent_writers_publish_one_tree_and_interrupted_temporaries_are_collectable() {
    let directory = Directory::new("concurrent");
    let client = Arc::new(FakeClient::new(
        "math",
        "1.0.0",
        BTreeMap::new(),
        package_archive("math", "1.0.0", &[]),
    ));
    let provider = Arc::new(provider(&directory, Arc::clone(&client)));
    let barrier = Arc::new(Barrier::new(8));
    let threads = (0..8)
        .map(|_| {
            let provider = Arc::clone(&provider);
            let barrier = Arc::clone(&barrier);
            std::thread::spawn(move || {
                barrier.wait();
                provider
                    .metadata(&PackageName::new("math").unwrap(), &Version::new(1, 0, 0))
                    .unwrap()
                    .root
            })
        })
        .collect::<Vec<_>>();
    let roots = threads
        .into_iter()
        .map(|thread| thread.join().unwrap())
        .collect::<Vec<_>>();
    assert!(roots.windows(2).all(|pair| pair[0] == pair[1]));
    assert_eq!(client.downloads.load(Ordering::Relaxed), 1);

    let digest = client.metadata.checksum.strip_prefix("sha256:").unwrap();
    fs::write(
        directory
            .0
            .join("cache/tmp")
            .join(format!("{digest}.download.dead.0")),
        b"partial",
    )
    .unwrap();
    fs::create_dir(
        directory
            .0
            .join("cache/tmp")
            .join(format!("{digest}.extract.dead.0")),
    )
    .unwrap();
    assert_eq!(
        cache(&directory, CacheLimits::default())
            .cleanup_temporaries()
            .unwrap(),
        2
    );
}

#[test]
fn online_resolution_then_offline_locked_materialization_works() {
    let directory = Directory::new("offline");
    let project = directory.0.join("project");
    fs::create_dir_all(project.join("src")).unwrap();
    fs::write(
        project.join("aether.toml"),
        manifest("app", "0.1.0", &[("math", "1")]),
    )
    .unwrap();
    fs::write(
        project.join("src/main.ae"),
        "import math\nint main() { return 0; }\n",
    )
    .unwrap();
    let client = Arc::new(FakeClient::new(
        "math",
        "1.0.0",
        BTreeMap::new(),
        package_archive("math", "1.0.0", &[]),
    ));
    let online = provider(&directory, Arc::clone(&client));
    let first = sync(&project, Some(&online)).unwrap();
    assert_eq!(first.packages.len(), 2);

    let digest = client.metadata.checksum.strip_prefix("sha256:").unwrap();
    let source = directory
        .0
        .join("cache/sources/sha256")
        .join(&digest[..2])
        .join(digest);
    make_writable_tree(&source);
    fs::remove_dir_all(&source).unwrap();
    let offline = RegistrySnapshotProvider::offline(cache(&directory, CacheLimits::default()));
    let second = sync(&project, Some(&offline)).unwrap();
    assert_eq!(second.packages.len(), 2);
    assert_eq!(client.downloads.load(Ordering::Relaxed), 1);

    fs::remove_file(
        directory
            .0
            .join("cache/objects/sha256")
            .join(&digest[..2])
            .join(digest),
    )
    .unwrap();
    make_writable_tree(&source);
    fs::remove_dir_all(source).unwrap();
    let error = sync(
        &project,
        Some(&RegistrySnapshotProvider::offline(cache(
            &directory,
            CacheLimits::default(),
        ))),
    )
    .unwrap_err();
    assert!(
        error.contains("offline cache is missing verified artifact"),
        "{error}"
    );
}

#[test]
fn offline_missing_metadata_fails_without_network() {
    let directory = Directory::new("offline-metadata");
    let provider = RegistrySnapshotProvider::offline(cache(&directory, CacheLimits::default()));
    let error = provider
        .versions(&PackageName::new("math").unwrap())
        .unwrap_err();
    assert!(error.contains("offline metadata"), "{error}");
}

#[test]
fn materialization_failure_does_not_change_existing_lock() {
    let directory = Directory::new("lock-atomic");
    let project = directory.0.join("project");
    fs::create_dir_all(project.join("src")).unwrap();
    fs::write(
        project.join("aether.toml"),
        manifest("app", "0.1.0", &[("math", "1")]),
    )
    .unwrap();
    fs::write(project.join("src/main.ae"), "int main(){return 0;}").unwrap();
    let archive = package_archive("math", "1.0.0", &[]);
    let good = Arc::new(FakeClient::new(
        "math",
        "1.0.0",
        BTreeMap::new(),
        archive.clone(),
    ));
    sync(&project, Some(&provider(&directory, good))).unwrap();
    let lock = fs::read(project.join("aether.lock")).unwrap();

    let mut bad = FakeClient::new("math", "1.0.0", BTreeMap::new(), archive);
    bad.metadata.checksum = format!("sha256:{}", "0".repeat(64));
    let failing = RegistrySnapshotProvider::new(
        Arc::new(bad),
        cache(&directory, CacheLimits::default()),
        RegistryPolicy::Online,
    );
    assert!(update(&project, Some(&failing)).is_err());
    assert_eq!(fs::read(project.join("aether.lock")).unwrap(), lock);
}
