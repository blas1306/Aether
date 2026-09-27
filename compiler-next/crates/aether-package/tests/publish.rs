//! Qualification for deterministic V1 source publication archives.

use std::fs;
use std::path::PathBuf;

use aether_package::{build_publication, inspect_publication};

struct Directory(PathBuf);

impl Directory {
    fn new(label: &str) -> Self {
        static SERIAL: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let path = std::env::temp_dir().join(format!(
            "aether-publish-{label}-{}-{}",
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
        fs::remove_dir_all(&self.0).unwrap();
    }
}

fn library(directory: &Directory, dependencies: &str) {
    directory.write(
        "aether.toml",
        &format!("[package]\nname='publishedLibrary'\nversion='1.2.3'\n{dependencies}\n"),
    );
    directory.write(
        "src/lib.ae",
        "package publishedLibrary; int answer(){return 42;}",
    );
}

#[test]
fn deterministic_archive_has_only_the_closed_v1_allowlist() {
    let first = Directory::new("first");
    let second = Directory::new("second");
    for directory in [&first, &second] {
        library(directory, "[dependencies]\nvectorMath='1.2'");
        directory.write("src/nested/value.ae", "package publishedLibrary.Nested;");
        directory.write("README.md", "read me");
        directory.write("LICENSE", "license");
        directory.write("aether.lock", "must not ship");
        directory.write("src/ignored.txt", "must not ship");
        directory.write("build/output", "must not ship");
    }
    let one = build_publication(&first.0).unwrap();
    let two = build_publication(&second.0).unwrap();
    assert_eq!(one.archive, two.archive);
    assert_eq!(one.checksum, two.checksum);
    assert_eq!(
        one.files,
        [
            "LICENSE",
            "README.md",
            "aether.toml",
            "src/lib.ae",
            "src/nested/value.ae"
        ]
    );
    let inspected = inspect_publication(&one.archive, one.archive.len() as u64).unwrap();
    assert_eq!(inspected.dependencies["vectorMath"], "1.2");
}

#[test]
fn publication_rejects_paths_applications_and_missing_library() {
    let path = Directory::new("path-dependency");
    library(&path, "[dependencies]\nlocal={path='../local'}");
    assert!(
        build_publication(&path.0)
            .unwrap_err()
            .contains("path dependency")
    );

    let application = Directory::new("application");
    application.write(
        "aether.toml",
        "[package]\nname='app'\nversion='1.0.0'\n[application]\nentry='src/tool.ae'\n",
    );
    application.write("src/lib.ae", "package app;");
    application.write("src/tool.ae", "int main(){return 0;}");
    assert!(
        build_publication(&application.0)
            .unwrap_err()
            .contains("application")
    );

    let missing = Directory::new("missing");
    missing.write(
        "aether.toml",
        "[package]\nname='missing'\nversion='1.0.0'\n",
    );
    assert!(build_publication(&missing.0).is_err());
}

#[test]
#[cfg(unix)]
fn publication_rejects_source_symlinks() {
    use std::os::unix::fs::symlink;

    let directory = Directory::new("symlink");
    library(&directory, "");
    directory.write("outside.ae", "package publishedLibrary;");
    symlink(
        directory.0.join("outside.ae"),
        directory.0.join("src/linked.ae"),
    )
    .unwrap();
    assert!(
        build_publication(&directory.0)
            .unwrap_err()
            .contains("symlink")
    );
}
