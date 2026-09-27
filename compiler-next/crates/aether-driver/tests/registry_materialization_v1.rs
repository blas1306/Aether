//! A real CAS-materialized registry source crosses the driver boundary at O0 and O2.

use std::collections::BTreeMap;
use std::fs;
use std::io::{Cursor, Read};
use std::path::PathBuf;
use std::sync::Arc;

use aether_driver::{
    CompilationOptions, DriverRequest, DriverResponse, OptimizationLevel, ProjectCheckRequest,
    ProjectPlan, execute,
};
use aether_package::{
    CacheLimits, PackageName, RegistryCache, RegistryClient, RegistryPolicy,
    RegistryProtocolMetadata, RegistrySnapshotProvider, RegistryVersion, sync,
};
use semver::Version;
use sha2::{Digest, Sha256};

struct Directory(PathBuf);

impl Directory {
    fn new() -> Self {
        static SERIAL: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let path = std::env::temp_dir().join(format!(
            "aether-driver-registry-{}-{}",
            std::process::id(),
            SERIAL.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
        ));
        fs::create_dir(&path).unwrap();
        Self(path)
    }
}

impl Drop for Directory {
    fn drop(&mut self) {
        make_writable(&self.0);
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn make_writable(path: &std::path::Path) {
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
                make_writable(&entry.path());
            }
        }
    }
}

struct Client {
    metadata: RegistryProtocolMetadata,
    archive: Vec<u8>,
}

impl RegistryClient for Client {
    fn versions(&self, _: &PackageName) -> Result<Vec<RegistryVersion>, String> {
        Ok(vec![RegistryVersion {
            version: self.metadata.version.clone(),
            yanked: false,
        }])
    }

    fn metadata(&self, _: &PackageName, _: &Version) -> Result<RegistryProtocolMetadata, String> {
        Ok(self.metadata.clone())
    }

    fn archive(&self, _: &RegistryProtocolMetadata) -> Result<Box<dyn Read + Send>, String> {
        Ok(Box::new(Cursor::new(self.archive.clone())))
    }
}

#[test]
fn cas_materialized_registry_package_compiles_at_o0_and_o2() {
    let directory = Directory::new();
    let project = directory.0.join("project");
    fs::create_dir_all(project.join("src")).unwrap();
    fs::write(
        project.join("aether.toml"),
        "[package]\nname = \"app\"\nversion = \"0.1.0\"\n\n[dependencies]\nmath = \"1\"\n",
    )
    .unwrap();
    fs::write(
        project.join("src/main.ae"),
        "import math; int main(){return math.answer();}",
    )
    .unwrap();
    let archive = tar_bytes(&[
        (
            "aether.toml",
            b"[package]\nname = \"math\"\nversion = \"1.0.0\"\n",
        ),
        ("src/lib.ae", b"package math; int answer(){return 0;}"),
    ]);
    let client = Client {
        metadata: RegistryProtocolMetadata {
            name: "math".to_owned(),
            version: "1.0.0".to_owned(),
            yanked: false,
            checksum: format!("sha256:{:x}", Sha256::digest(&archive)),
            dependencies: BTreeMap::new(),
            archive_size: archive.len() as u64,
        },
        archive,
    };
    let cache = RegistryCache::new(directory.0.join("cache"), CacheLimits::default()).unwrap();
    let provider = RegistrySnapshotProvider::new(Arc::new(client), cache, RegistryPolicy::Online);
    let graph = sync(&project, Some(&provider)).unwrap();
    let plan = ProjectPlan::resolved(graph.root, &graph.packages).unwrap();
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let response = execute(DriverRequest::CheckProject(ProjectCheckRequest {
            input: plan.clone(),
            compilation: CompilationOptions {
                optimization,
                emits: Vec::new(),
            },
        }))
        .unwrap();
        assert!(matches!(response, DriverResponse::Checked(_)));
    }
}

fn tar_bytes(entries: &[(&str, &[u8])]) -> Vec<u8> {
    let mut archive = Vec::new();
    for (path, contents) in entries {
        let mut header = [0_u8; 512];
        header[..path.len()].copy_from_slice(path.as_bytes());
        header[100..108].copy_from_slice(b"0000444\0");
        header[108..116].copy_from_slice(b"0000000\0");
        header[116..124].copy_from_slice(b"0000000\0");
        write_octal(&mut header[124..136], contents.len() as u64);
        header[136..148].copy_from_slice(b"00000000000\0");
        header[148..156].fill(b' ');
        header[156] = b'0';
        header[257..263].copy_from_slice(b"ustar\0");
        header[263..265].copy_from_slice(b"00");
        let checksum: u64 = header.iter().map(|byte| u64::from(*byte)).sum();
        let checksum = format!("{checksum:06o}\0 ");
        header[148..156].copy_from_slice(checksum.as_bytes());
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
